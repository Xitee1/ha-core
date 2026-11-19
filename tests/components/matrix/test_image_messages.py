"""Test MatrixBot's handling of image messages in matrix rooms."""

from copy import deepcopy
from typing import Any
from unittest.mock import patch

from nio import MatrixRoom, RoomMessageImage, RoomMessageText
import pytest

from homeassistant.components.matrix import (
    CONF_COMMANDS,
    CONF_EXPRESSION,
    CONF_ROOMS,
    MatrixBot,
    RoomID,
)
from homeassistant.components.matrix.const import DOMAIN
from homeassistant.components.notify import DOMAIN as NOTIFY_DOMAIN
from homeassistant.const import CONF_NAME
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import (
    MOCK_CONFIG_DATA,
    TEST_BAD_ROOM,
    TEST_EVENT_ID,
    TEST_MEDIA_CONTENT_ID,
    TEST_MXC_URI,
    TEST_ROOM_A_ID,
    TEST_ROOM_C_ID,
    TEST_SENDER,
    create_image_message,
)

# Room C additionally has a command that matches any text, including "".
CATCH_ALL_ROOM = TEST_ROOM_C_ID
CATCH_ALL_COMMAND = {
    CONF_EXPRESSION: "(?s)(?P<text>.*)",
    CONF_NAME: "CatchAllEventName",
    CONF_ROOMS: [CATCH_ALL_ROOM],
}
MEDIA_DATA = {
    "media_content_id": TEST_MEDIA_CONTENT_ID,
    "media_content_type": "image/jpeg",
}


@pytest.fixture
async def matrix_bot(
    hass: HomeAssistant, mock_client, mock_save_json, mock_allowed_path
) -> MatrixBot:
    """Set up Matrix with an additional catch-all expression command."""
    config = deepcopy(MOCK_CONFIG_DATA)
    config[DOMAIN][CONF_COMMANDS].append(CATCH_ALL_COMMAND)

    assert await async_setup_component(hass, DOMAIN, config)
    assert await async_setup_component(hass, NOTIFY_DOMAIN, config)
    await hass.async_block_till_done()
    assert isinstance(matrix_bot := hass.data[DOMAIN], MatrixBot)
    await hass.async_start()
    return matrix_bot


async def _handle_message(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    room_id: str,
    message: RoomMessageText | RoomMessageImage,
) -> None:
    """Pass a message from a room to the MatrixBot."""
    room = MatrixRoom(room_id=room_id, own_user_id=matrix_bot._mx_id)
    await matrix_bot._handle_room_message(room, message)
    await hass.async_block_till_done()


def _expected_event_data(
    room_id: RoomID, command: str, args: dict[str, str] | list[str]
) -> dict[str, Any]:
    """Return the expected event data of a command."""
    return {
        "command": command,
        "sender": TEST_SENDER,
        "room": room_id,
        "event_id": TEST_EVENT_ID,
        "thread_parent": TEST_EVENT_ID,
        "args": args,
    }


@pytest.mark.parametrize(
    ("caption", "command", "args"),
    [
        pytest.param(
            "My name is FakeName",
            "ExpressionTriggerEventName",
            {"name": "FakeName"},
            id="expression",
        ),
        pytest.param(
            "!WordTrigger arg1 arg2",
            "WordTriggerEventName",
            ["arg1", "arg2"],
            id="word",
        ),
    ],
)
async def test_image_caption_command(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
    caption: str,
    command: str,
    args: dict[str, str] | list[str],
) -> None:
    """Test that an image caption triggers commands with the media added."""
    message = create_image_message(
        body=caption, filename="photo.jpg", info={"mimetype": "image/jpeg"}
    )

    await _handle_message(hass, matrix_bot, TEST_ROOM_A_ID, message)

    assert len(command_events) == 1
    assert command_events[0].data == (
        _expected_event_data(TEST_ROOM_A_ID, command, args) | MEDIA_DATA
    )
    assert matrix_bot.is_received_media(TEST_MXC_URI)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param({"body": "photo.jpg"}, id="without_filename"),
        pytest.param(
            {"body": "photo.jpg", "filename": "photo.jpg"}, id="same_filename"
        ),
    ],
)
async def test_image_without_caption(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
    content: dict[str, str],
) -> None:
    """Test that an image without caption is matched against an empty text."""
    message = create_image_message(info={"mimetype": "image/jpeg"}, **content)

    await _handle_message(hass, matrix_bot, CATCH_ALL_ROOM, message)

    assert len(command_events) == 1
    assert command_events[0].data == (
        _expected_event_data(CATCH_ALL_ROOM, "CatchAllEventName", {"text": ""})
        | MEDIA_DATA
    )


async def test_image_without_mimetype(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
) -> None:
    """Test that the media content type is omitted if the event has none."""
    message = create_image_message(body="photo.jpg")

    await _handle_message(hass, matrix_bot, CATCH_ALL_ROOM, message)

    assert len(command_events) == 1
    assert command_events[0].data == (
        _expected_event_data(CATCH_ALL_ROOM, "CatchAllEventName", {"text": ""})
        | {"media_content_id": TEST_MEDIA_CONTENT_ID}
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            {"body": "Hello there", "filename": "photo.jpg"}, id="caption_no_match"
        ),
        pytest.param({"body": "photo.jpg"}, id="without_caption"),
    ],
)
async def test_image_non_commands(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
    content: dict[str, str],
) -> None:
    """Test that images without a matching caption trigger nothing."""
    message = create_image_message(**content)

    await _handle_message(hass, matrix_bot, TEST_ROOM_A_ID, message)

    assert len(command_events) == 0
    assert matrix_bot.is_received_media(TEST_MXC_URI)


@pytest.mark.parametrize(
    ("room_id", "content"),
    [
        pytest.param(TEST_BAD_ROOM, {"url": TEST_MXC_URI}, id="not_listening_room"),
        pytest.param(
            CATCH_ALL_ROOM, {"url": "https://example.com/photo.jpg"}, id="no_mxc_url"
        ),
        pytest.param(
            CATCH_ALL_ROOM,
            {
                "url": TEST_MXC_URI,
                "m.new_content": {
                    "msgtype": "m.image",
                    "body": "photo.jpg",
                    "url": TEST_MXC_URI,
                },
                "m.relates_to": {"rel_type": "m.replace", "event_id": "original_id"},
            },
            id="edit",
        ),
    ],
)
async def test_image_ignored(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
    room_id: str,
    content: dict[str, Any],
) -> None:
    """Test that images are ignored outside listening rooms, without mxc URL or as edit."""
    message = create_image_message(body="photo.jpg", **content)

    await _handle_message(hass, matrix_bot, room_id, message)

    assert len(command_events) == 0
    assert not matrix_bot.is_received_media(content["url"])


async def test_text_message_unchanged(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
    command_events: list[Event],
) -> None:
    """Test that text messages don't get media data."""
    message = RoomMessageText(
        body="Some text",
        formatted_body=None,
        format=None,
        source={
            "event_id": TEST_EVENT_ID,
            "sender": TEST_SENDER,
            "origin_server_ts": 123456789,
        },
    )

    await _handle_message(hass, matrix_bot, CATCH_ALL_ROOM, message)

    assert len(command_events) == 1
    assert command_events[0].data == _expected_event_data(
        CATCH_ALL_ROOM, "CatchAllEventName", {"text": "Some text"}
    )


async def test_received_media_limit(
    hass: HomeAssistant,
    matrix_bot: MatrixBot,
) -> None:
    """Test that only the most recently received media is remembered."""
    with patch.object(matrix_bot._received_media, "size_limit", 2):
        for media_id in ("First", "Second", "Third"):
            message = create_image_message(
                body="photo.jpg", url=f"mxc://example.com/{media_id}"
            )
            await _handle_message(hass, matrix_bot, TEST_ROOM_A_ID, message)

    assert not matrix_bot.is_received_media("mxc://example.com/First")
    assert matrix_bot.is_received_media("mxc://example.com/Second")
    assert matrix_bot.is_received_media("mxc://example.com/Third")
