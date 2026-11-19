"""Test the Matrix media source."""

from unittest.mock import AsyncMock, patch

from nio import DownloadError, MatrixRoom, MemoryDownloadResponse
import pytest

from homeassistant.components import media_source
from homeassistant.components.matrix import MatrixBot
from homeassistant.components.matrix.const import DOMAIN
from homeassistant.components.media_player import BrowseError
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import (
    TEST_MEDIA_CONTENT_ID,
    TEST_MXC_URI,
    TEST_ROOM_A_ID,
    create_image_message,
)


@pytest.fixture(autouse=True)
async def setup_media_source(hass: HomeAssistant) -> None:
    """Set up media source."""
    assert await async_setup_component(hass, media_source.DOMAIN, {})


async def _receive_image(hass: HomeAssistant, matrix_bot: MatrixBot) -> None:
    """Receive the test image in a listening room."""
    room = MatrixRoom(room_id=TEST_ROOM_A_ID, own_user_id=matrix_bot._mx_id)
    await matrix_bot._handle_room_message(room, create_image_message(body="photo.jpg"))
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "content_type",
    [
        pytest.param("image/jpeg", id="plain"),
        pytest.param("image/jpeg; charset=binary", id="with_parameters"),
    ],
)
async def test_get_media_image(
    hass: HomeAssistant, matrix_bot: MatrixBot, content_type: str
) -> None:
    """Test getting a received image."""
    await _receive_image(hass, matrix_bot)

    with patch.object(
        matrix_bot._client,
        "download",
        AsyncMock(
            return_value=MemoryDownloadResponse(
                body=b"image-bytes", content_type=content_type, filename=None
            )
        ),
    ) as mock_download:
        image = await media_source.async_get_media_image(hass, TEST_MEDIA_CONTENT_ID)

    mock_download.assert_awaited_once_with(mxc=TEST_MXC_URI)
    assert image == media_source.MediaImage(b"image-bytes", "image/jpeg")


async def test_get_media_image_download_error(
    hass: HomeAssistant, matrix_bot: MatrixBot
) -> None:
    """Test a failing download of a received image."""
    await _receive_image(hass, matrix_bot)

    with (
        patch.object(
            matrix_bot._client,
            "download",
            AsyncMock(return_value=DownloadError("Not found", "M_NOT_FOUND")),
        ),
        pytest.raises(media_source.Unresolvable) as exc_info,
    ):
        await media_source.async_get_media_image(hass, TEST_MEDIA_CONTENT_ID)

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "media_download_failed"


async def test_get_media_image_unknown_media(
    hass: HomeAssistant, matrix_bot: MatrixBot
) -> None:
    """Test that media which was not received in a listening room is not served."""
    with (
        patch.object(matrix_bot._client, "download", AsyncMock()) as mock_download,
        pytest.raises(media_source.Unresolvable) as exc_info,
    ):
        await media_source.async_get_media_image(hass, TEST_MEDIA_CONTENT_ID)

    mock_download.assert_not_called()
    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "unknown_media"


async def test_get_media_image_unsupported_media_type(
    hass: HomeAssistant, matrix_bot: MatrixBot
) -> None:
    """Test that downloaded media which is not an image is not served."""
    await _receive_image(hass, matrix_bot)

    with (
        patch.object(
            matrix_bot._client,
            "download",
            AsyncMock(
                return_value=MemoryDownloadResponse(
                    body=b"pdf-bytes", content_type="application/pdf", filename=None
                )
            ),
        ),
        pytest.raises(media_source.Unresolvable) as exc_info,
    ):
        await media_source.async_get_media_image(hass, TEST_MEDIA_CONTENT_ID)

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "unsupported_media_type"


async def test_resolve_media(hass: HomeAssistant, matrix_bot: MatrixBot) -> None:
    """Test that received images can't be resolved to a playable URL."""
    await _receive_image(hass, matrix_bot)

    with pytest.raises(media_source.Unresolvable) as exc_info:
        await media_source.async_resolve_media(hass, TEST_MEDIA_CONTENT_ID, None)

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "media_not_playable"


async def test_browse_media(hass: HomeAssistant, matrix_bot: MatrixBot) -> None:
    """Test browsing the Matrix media source."""
    await _receive_image(hass, matrix_bot)

    item = await media_source.async_browse_media(hass, "media-source://matrix")

    assert item.title == "Matrix"
    assert item.can_expand
    assert item.children == []

    with pytest.raises(BrowseError):
        await media_source.async_browse_media(hass, TEST_MEDIA_CONTENT_ID)
