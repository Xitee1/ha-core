"""Expose images received in Matrix rooms as media sources."""

from typing import override

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaImage,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from . import MatrixBot, MatrixDownloadError
from .const import DOMAIN


async def async_get_media_source(hass: HomeAssistant) -> MatrixMediaSource:
    """Set up Matrix media source."""
    return MatrixMediaSource(hass)


class MatrixMediaSource(MediaSource):
    """Provide images received in Matrix rooms as media sources."""

    name: str = "Matrix"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize MatrixMediaSource."""
        super().__init__(DOMAIN)
        self.hass = hass

    @override
    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve media to a url."""
        raise Unresolvable(
            translation_domain=DOMAIN,
            translation_key="media_not_playable",
            translation_placeholders={"media_content_id": item.media_source_id},
        )

    @override
    async def async_get_media_image(self, item: MediaSourceItem) -> MediaImage:
        """Return an image received in a listening room."""
        bot: MatrixBot = self.hass.data[DOMAIN]
        mxc_uri = f"mxc://{item.identifier}"

        if not bot.is_received_media(mxc_uri):
            raise Unresolvable(
                translation_domain=DOMAIN,
                translation_key="unknown_media",
                translation_placeholders={"media_content_id": item.media_source_id},
            )

        try:
            content, content_type = await bot.async_download_media(mxc_uri)
        except MatrixDownloadError as err:
            raise Unresolvable(
                translation_domain=DOMAIN,
                translation_key="media_download_failed",
                translation_placeholders={"mxc_uri": mxc_uri},
            ) from err

        mime_type = content_type.partition(";")[0].strip()
        if not mime_type.startswith("image/"):
            raise Unresolvable(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={
                    "mxc_uri": mxc_uri,
                    "content_type": content_type,
                },
            )

        return MediaImage(content, mime_type)

    @override
    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Return an empty root, received images can't be played or listed."""
        if item.identifier:
            raise BrowseError(
                translation_domain=DOMAIN,
                translation_key="unknown_media",
                translation_placeholders={"media_content_id": item.media_source_id},
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.APP,
            media_content_type="",
            title="Matrix",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.IMAGE,
            children=[],
        )
