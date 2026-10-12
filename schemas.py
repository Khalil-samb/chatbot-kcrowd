from pydantic import BaseModel


class MessageHistorique(BaseModel):
    role: str  # "user" ou "assistant"
    content: str


class RequeteChat(BaseModel):
    message: str
    historique: list[MessageHistorique] = []


class LienReponse(BaseModel):
    label: str
    path: str


class ReponseChat(BaseModel):
    reponse: str
    liens: list[LienReponse]