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

class RequeteVocale(BaseModel):
    audio_base64: str
    mime_type: str = "audio/wav"
    historique: list[MessageHistorique] = []


class ReponseVocale(BaseModel):
    transcription: str
    langue: str
    reponse: str
    liens: list[LienReponse]


class RequeteVoix(BaseModel):
    texte: str
