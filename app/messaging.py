from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from nats.aio.client import Client as NATS
from nats.errors import TimeoutError as NATSTimeout
from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.client import UnifiedMessaging
from unimessaging.broker.config import MessagingConfig
from unimessaging.broker.registry import HandlerRegistry

_broker: Optional[UnifiedMessageBroker] = None
_client: Optional[UnifiedMessaging] = None
logger = logging.getLogger("messaging.nats")


def _decode_payload(data: Any) -> Any:
    if isinstance(data, bytes):
        try:
            return json.loads(data.decode())
        except Exception:
            return None
    return data


def _payload_context(data: Any) -> Dict[str, Any]:
    payload = _decode_payload(data)
    if not isinstance(payload, dict):
        return {}

    context: Dict[str, Any] = {}
    for key in (
        "event",
        "event_type",
        "aggregate_id",
        "source_id",
        "id",
        "order_id",
        "reservation_id",
        "user_id",
        "child_id",
    ):
        value = payload.get(key)
        if value is not None:
            context[key] = value

    for key in ("aggregate", "user", "child", "reservation", "order"):
        nested = payload.get(key)
        if isinstance(nested, dict) and nested.get("id") is not None:
            context.setdefault(f"{key}_id", nested["id"])

    return context


class ReconnectingNATSAdapter:
    def __init__(self, cfg: MessagingConfig) -> None:
        self.cfg = cfg
        self.nc: Optional[NATS] = None
        self.js: Any = None
        self._subs: List[Any] = []

    async def start(self) -> None:
        self.nc = NATS()
        logger.info(
            "NATS connect start: service=%s url=%s durable=%s stream=%s subjects=%s max_reconnect_attempts=%s reconnect_time_wait=%s",
            self.cfg.name,
            self.cfg.url,
            self.cfg.enable_durable,
            getattr(self.cfg, "stream_name", None),
            list(getattr(self.cfg, "stream_subjects", []) or []),
            -1,
            2,
        )
        await self.nc.connect(
            self.cfg.url,
            name=self.cfg.name,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
            closed_cb=self._on_closed,
            error_cb=self._on_error,
        )
        if self.cfg.enable_durable:
            self.js = self.nc.jetstream()
            if self.cfg.stream_name and self.cfg.stream_subjects:
                try:
                    await self.js.add_stream(
                        name=self.cfg.stream_name,
                        subjects=list(self.cfg.stream_subjects),
                    )
                    logger.info(
                        "JetStream stream ensured: service=%s stream=%s subjects=%s",
                        self.cfg.name,
                        self.cfg.stream_name,
                        list(self.cfg.stream_subjects),
                    )
                except Exception as exc:
                    logger.debug(
                        "JetStream stream ensure skipped: service=%s stream=%s err=%s",
                        self.cfg.name,
                        self.cfg.stream_name,
                        exc,
                    )
        logger.info("NATS connected: service=%s js=%s", self.cfg.name, bool(self.js))

    async def stop(self) -> None:
        if self.nc:
            logger.info("NATS stopping: service=%s", self.cfg.name)
            await self.nc.drain()
            logger.info("NATS stopped: service=%s", self.cfg.name)

    async def publish(
        self, subject: str, data: Any = None, headers: Optional[Dict[str, str]] = None
    ) -> None:
        payload = self._to_bytes(data)
        hdrs = self._headers(headers)
        logger.info(
            "NATS publish: service=%s subject=%s bytes=%d js=%s headers=%s context=%s",
            self.cfg.name,
            subject,
            len(payload or b""),
            bool(self.js),
            dict(hdrs or {}),
            _payload_context(data),
        )
        if self.js:
            await self.js.publish(subject, payload, headers=hdrs)
        else:
            await self.nc.publish(subject, payload, headers=hdrs)

    async def subscribe(self, subject: str, handler: Callable, queue: Optional[str] = None) -> Any:
        async def _on_msg(msg: Any) -> None:
            meta = {"subject": msg.subject, "headers": dict(msg.headers or {})}
            logger.info(
                "NATS recv: service=%s subject=%s bytes=%d queue=%s headers=%s context=%s",
                self.cfg.name,
                msg.subject,
                len(msg.data or b""),
                queue,
                meta["headers"],
                _payload_context(msg.data),
            )
            await handler(msg.data, meta)

        sid = await self.nc.subscribe(subject, queue=queue, cb=_on_msg)
        self._subs.append(sid)
        logger.info(
            "NATS subscribed: service=%s subject=%s queue=%s sid=%s",
            self.cfg.name,
            subject,
            queue,
            sid,
        )
        return sid

    async def request(
        self,
        subject: str,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            payload = self._to_bytes(data)
            hdrs = self._headers(headers)
            wait_timeout = timeout or self.cfg.request_timeout
            logger.info(
                "NATS request: service=%s subject=%s bytes=%d timeout=%s headers=%s context=%s",
                self.cfg.name,
                subject,
                len(payload or b""),
                wait_timeout,
                dict(hdrs or {}),
                _payload_context(data),
            )
            msg = await self.nc.request(
                subject,
                payload,
                wait_timeout,
                headers=hdrs,
            )
            logger.info(
                "NATS reply: service=%s subject=%s bytes=%d headers=%s context=%s",
                self.cfg.name,
                msg.subject,
                len(msg.data or b""),
                dict(msg.headers or {}),
                _payload_context(msg.data),
            )
            return {
                "data": msg.data,
                "headers": dict(msg.headers or {}),
                "subject": msg.subject,
            }
        except NATSTimeout as exc:
            logger.warning(
                "NATS request timeout: service=%s subject=%s err=%s",
                self.cfg.name,
                subject,
                exc,
            )
            raise TimeoutError(str(exc)) from exc

    async def reply(self, subject: str, fn: Callable, queue: Optional[str] = None) -> Any:
        async def _on_req(msg: Any) -> None:
            try:
                logger.info(
                    "NATS serve: service=%s subject=%s bytes=%d queue=%s context=%s",
                    self.cfg.name,
                    msg.subject,
                    len(msg.data or b""),
                    queue,
                    _payload_context(msg.data),
                )
                res = await fn(msg.data, {"subject": msg.subject})
                if msg.reply:
                    out = self._to_bytes(res)
                    await self.nc.publish(msg.reply, out)
                    logger.info(
                        "NATS served: service=%s reply_subject=%s bytes=%d context=%s",
                        self.cfg.name,
                        msg.reply,
                        len(out or b""),
                        _payload_context(res),
                    )
            except Exception as exc:
                logger.exception(
                    "NATS reply handler failed: service=%s subject=%s err=%s",
                    self.cfg.name,
                    msg.subject,
                    exc,
                )

        sid = await self.nc.subscribe(subject, queue=queue, cb=_on_req)
        self._subs.append(sid)
        logger.info(
            "NATS replier started: service=%s subject=%s queue=%s sid=%s",
            self.cfg.name,
            subject,
            queue,
            sid,
        )
        return sid

    async def scatter_gather(
        self,
        subject: str,
        data: Any,
        window: float = 0.3,
        headers: Optional[Dict[str, str]] = None,
        max_msgs: Optional[int] = None,
    ) -> List[bytes]:
        inbox = await self.nc.new_inbox()
        results: List[bytes] = []
        done = asyncio.Event()

        async def on_reply(msg: Any) -> None:
            results.append(msg.data)
            if max_msgs and len(results) >= max_msgs:
                done.set()

        sid = await self.nc.subscribe(inbox, cb=on_reply)
        logger.info(
            "NATS scatter start: service=%s subject=%s inbox=%s window=%s max_msgs=%s context=%s",
            self.cfg.name,
            subject,
            inbox,
            window,
            max_msgs,
            _payload_context(data),
        )
        await self.nc.publish(
            subject, self._to_bytes(data), reply=inbox, headers=self._headers(headers)
        )
        try:
            await asyncio.wait_for(done.wait(), timeout=window)
        except asyncio.TimeoutError:
            pass
        await self.nc.unsubscribe(sid)
        logger.info(
            "NATS scatter done: service=%s subject=%s replies=%d",
            self.cfg.name,
            subject,
            len(results),
        )
        return results

    async def pull_consume(
        self,
        subject: str,
        durable: str,
        handler: Callable,
        batch: int = 10,
        timeout: float = 1.0,
    ) -> None:
        if not self.js:
            raise RuntimeError("JetStream not enabled")
        while True:
            try:
                sub = await self.js.pull_subscribe(subject, durable=durable)
                logger.info(
                    "JetStream pull consumer bound: service=%s subject=%s durable=%s batch=%s timeout=%s",
                    self.cfg.name,
                    subject,
                    durable,
                    batch,
                    timeout,
                )
                while True:
                    try:
                        msgs = await sub.fetch(batch, timeout=timeout)
                    except NATSTimeout:
                        continue
                    for msg in msgs:
                        try:
                            logger.info(
                                "JetStream recv: service=%s subject=%s durable=%s bytes=%d context=%s",
                                self.cfg.name,
                                msg.subject,
                                durable,
                                len(msg.data or b""),
                                _payload_context(msg.data),
                            )
                            await handler(msg.data, {"subject": msg.subject})
                            await msg.ack()
                            logger.info(
                                "JetStream ack: service=%s subject=%s durable=%s",
                                self.cfg.name,
                                msg.subject,
                                durable,
                            )
                        except Exception:
                            logger.warning(
                                "JetStream nak: service=%s subject=%s durable=%s",
                                self.cfg.name,
                                msg.subject,
                                durable,
                            )
                            await msg.nak()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "JetStream pull consumer reset: service=%s subject=%s durable=%s err=%s",
                    self.cfg.name,
                    subject,
                    durable,
                    exc,
                )
                await asyncio.sleep(getattr(self.cfg, "reconnect_time_wait", 2) or 2)

    async def _on_disconnected(self) -> None:
        logger.warning("NATS disconnected: service=%s", self.cfg.name)

    async def _on_reconnected(self) -> None:
        logger.info("NATS reconnected: service=%s", self.cfg.name)

    async def _on_closed(self) -> None:
        logger.warning("NATS closed: service=%s", self.cfg.name)

    async def _on_error(self, exc: Exception) -> None:
        logger.warning("NATS async error: service=%s err=%s", self.cfg.name, exc)

    def _to_bytes(self, data: Any) -> bytes:
        if data is None:
            return b""
        if isinstance(data, bytes):
            return data
        return json.dumps(data).encode()

    def _headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        out = dict(self.cfg.default_headers)
        if headers:
            out.update(headers)
        return out


class ReconnectingUnifiedMessaging(UnifiedMessaging):
    def __init__(self, cfg: MessagingConfig) -> None:
        self.cfg = cfg
        self.adapter = ReconnectingNATSAdapter(cfg)


def _create_client(service_name: str, *, url: str, enable_durable: bool) -> ReconnectingUnifiedMessaging:
    cfg = MessagingConfig(
        backend="nats",
        url=url,
        name=service_name,
        enable_durable=enable_durable,
        default_headers={"service": service_name},
    )
    return ReconnectingUnifiedMessaging(cfg)


async def start_messaging(
    *,
    subjects: List[str],
    service_name: str,
    url: str = "nats://localhost:4222",
    enable_durable: bool = False,
    registry: Optional[HandlerRegistry] = None,
) -> UnifiedMessageBroker:
    global _broker, _client

    broker = UnifiedMessageBroker(
        subjects=subjects,
        service_name=service_name,
        url=url,
        enable_durable=enable_durable,
        registry=registry,
        client=_create_client(service_name, url=url, enable_durable=enable_durable),
    )
    await broker.start()
    _broker = broker
    _client = broker.client
    return broker


def get_messaging() -> Optional[UnifiedMessaging]:
    return _client


async def stop_messaging() -> None:
    global _broker, _client

    if _broker is not None:
        try:
            await _broker.stop()
        except Exception:
            pass
    _broker = None
    _client = None
