from datetime import datetime
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    bio: str = Field(default="", max_length=255)


class PostCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class ReplyCreate(BaseModel):
    post_id: int
    content: str = Field(min_length=1, max_length=1000)


class FeedItem(BaseModel):
    post_id: int
    author: str
    content: str
    created_at: datetime
    replies: list[dict]
