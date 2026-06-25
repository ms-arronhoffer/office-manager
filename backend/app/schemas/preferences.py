from pydantic import BaseModel


class UserPreferences(BaseModel):
    theme: str = "light"
    density: str = "comfortable"
    font_size: str = "medium"
    page_sizes: dict[str, int] = {}
    visible_columns: dict[str, list[str]] = {}
    default_filters: dict[str, dict] = {}
    dashboard_widgets: dict[str, bool] = {}
    navigation_open: bool = True
    pinned_offices: list[dict] = []
    saved_filters: dict[str, list[dict]] = {}
