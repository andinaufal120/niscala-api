"""Base model shared by every API schema."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

VERSION_DESCRIPTION = (
    "Rises by one with every edit. Send it back in the If-Match header, "
    'as a quoted number such as "3", to refuse an edit made on stale data.'
)


class ApiModel(BaseModel):
    """Exposes snake_case attributes as camelCase fields on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, validate_by_alias=True
    )
