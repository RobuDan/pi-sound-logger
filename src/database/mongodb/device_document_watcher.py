import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any


class DeviceDocumentWatcher:
    def __init__(
        self,
        collection: Any,
        device_id: str,
        on_updated_parameters: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_audio_trigger: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        self.collection = collection
        self.device_id = device_id
        self.on_updated_parameters = on_updated_parameters
        self.on_audio_trigger = on_audio_trigger

    async def run(self) -> None:
        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "documentKey._id": self.device_id,
                    "operationType": "update",
                }
            }
        ]

        try:
            async with self.collection.watch(pipeline) as stream:
                async for change in stream:
                    updated_fields: dict[str, Any] = (
                        change.get("updateDescription", {}).get("updatedFields", {})
                    )

                    if "updated_parameters" in updated_fields:
                        updated_params = updated_fields.get("updated_parameters")
                        if updated_params and self.on_updated_parameters:
                            logging.info(f"Detected change in updated_parameters: {updated_params}")
                            await self.on_updated_parameters(updated_params)

                    if "audio_trigger" in updated_fields:
                        new_trigger_value = updated_fields.get("audio_trigger")
                        if self.on_audio_trigger:
                            logging.info(f"Detected change in audio_trigger: {new_trigger_value}")
                            await self.on_audio_trigger(new_trigger_value)

        except asyncio.CancelledError:
            logging.info("DeviceDocumentWatcher task was cancelled")
            raise
        except Exception as e:
            logging.error(f"Error in DeviceDocumentWatcher: {e}")