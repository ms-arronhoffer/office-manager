from pydantic import BaseModel


class AssistantRequest(BaseModel):
    prompt: str


class AssistantResponse(BaseModel):
    """Result of parsing a plain-English assistant request.

    ``action_type`` tells the client how to proceed:

    * ``navigate`` — follow ``route`` immediately (read-only),
    * ``search`` — run an entity search for ``query`` immediately (read-only),
    * ``action`` — a *mutating* proposal in ``proposal`` that the client must
      confirm before submitting to the referenced typed endpoint,
    * ``none`` — the request was not understood.
    """

    intent: str
    action_type: str
    route: str | None = None
    query: str | None = None
    proposal: dict | None = None
    confirmation_required: bool = False
    permitted: bool = True
    message: str
    model: str
