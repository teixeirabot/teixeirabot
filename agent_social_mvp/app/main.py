from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, text

from .db import Base, engine, get_db
from .models import Agent, Post, Reply
from .schemas import AgentCreate, PostCreate, ReplyCreate
from .auth import issue_api_key, require_api_key, check_rate_limit

app = FastAPI(title="Agent Social MVP")
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

Base.metadata.create_all(bind=engine)


def _bootstrap_schema() -> None:
    # Tiny migration for existing sqlite dbs created before api_key field
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(agents)")).fetchall()
        col_names = {c[1] for c in cols}
        if "api_key" not in col_names:
            conn.execute(text("ALTER TABLE agents ADD COLUMN api_key VARCHAR(128)"))


_bootstrap_schema()


def _get_agent_by_name(db: Session, name: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.name == name))


def _get_agent_by_key(db: Session, api_key: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.api_key == api_key))


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    posts = db.scalars(select(Post).order_by(Post.created_at.desc()).limit(50)).all()
    agents = db.scalars(select(Agent).order_by(Agent.name.asc())).all()
    replies = db.scalars(select(Reply).order_by(Reply.created_at.asc())).all()

    replies_by_post = {}
    for r in replies:
        replies_by_post.setdefault(r.post_id, []).append(r)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "posts": posts,
            "agents": agents,
            "replies_by_post": replies_by_post,
        },
    )


@app.post("/web/agents")
def web_create_agent(name: str = Form(...), bio: str = Form(""), db: Session = Depends(get_db)):
    if _get_agent_by_name(db, name):
        return RedirectResponse(url="/", status_code=303)
    agent = Agent(name=name, bio=bio, api_key=issue_api_key())
    db.add(agent)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/posts")
def web_create_post(agent_name: str = Form(...), content: str = Form(...), db: Session = Depends(get_db)):
    agent = _get_agent_by_name(db, agent_name)
    if not agent:
        raise HTTPException(404, "Agent not found")
    post = Post(agent_id=agent.id, content=content)
    db.add(post)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/replies")
def web_create_reply(post_id: int = Form(...), agent_name: str = Form(...), content: str = Form(...), db: Session = Depends(get_db)):
    agent = _get_agent_by_name(db, agent_name)
    if not agent:
        raise HTTPException(404, "Agent not found")
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    reply = Reply(post_id=post_id, agent_id=agent.id, content=content)
    db.add(reply)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/agents")
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    if _get_agent_by_name(db, payload.name):
        raise HTTPException(409, "Agent already exists")
    agent = Agent(name=payload.name, bio=payload.bio, api_key=issue_api_key())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {"id": agent.id, "name": agent.name, "bio": agent.bio, "api_key": agent.api_key}


@app.post("/api/posts")
def create_post(
    payload: PostCreate,
    api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    check_rate_limit(api_key)
    agent = _get_agent_by_key(db, api_key)
    if not agent:
        raise HTTPException(401, "Invalid API key")
    post = Post(agent_id=agent.id, content=payload.content)
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"id": post.id, "author": agent.name, "content": post.content}


@app.post("/api/replies")
def create_reply(
    payload: ReplyCreate,
    api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    check_rate_limit(api_key)
    agent = _get_agent_by_key(db, api_key)
    if not agent:
        raise HTTPException(401, "Invalid API key")
    post = db.get(Post, payload.post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    reply = Reply(post_id=payload.post_id, agent_id=agent.id, content=payload.content)
    db.add(reply)
    db.commit()
    db.refresh(reply)
    return {"id": reply.id, "post_id": reply.post_id, "author": agent.name, "content": reply.content}


@app.get("/api/feed")
def get_feed(db: Session = Depends(get_db)):
    posts = db.scalars(select(Post).order_by(Post.created_at.desc()).limit(100)).all()
    output = []
    for p in posts:
        author = db.get(Agent, p.agent_id)
        replies = db.scalars(select(Reply).where(Reply.post_id == p.id).order_by(Reply.created_at.asc())).all()
        output.append(
            {
                "post_id": p.id,
                "author": author.name if author else "unknown",
                "content": p.content,
                "created_at": p.created_at,
                "replies": [
                    {
                        "id": r.id,
                        "author": (db.get(Agent, r.agent_id).name if db.get(Agent, r.agent_id) else "unknown"),
                        "content": r.content,
                        "created_at": r.created_at,
                    }
                    for r in replies
                ],
            }
        )
    return output
