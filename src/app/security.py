"""Bearer authentication scheme declared on every operation that needs a session."""

from fastapi.security import HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="bearerAuth", bearerFormat="JWT", auto_error=False
)
