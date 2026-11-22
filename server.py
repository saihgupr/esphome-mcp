#!/usr/bin/env python3
import os
import sys
import json
import asyncio
import time
import httpx
from mcp.server.mcpserver import MCPServer

# Initialize MCP Server
mcp = MCPServer("esphome")

ESPHOME_HOST = os.environ.get("ESPHOME_HOST", "192.168.1.4")
ESPHOME_PORT = int(os.environ.get("ESPHOME_PORT", "6052"))

async def _send_ws_command(command: str, args: dict = None, timeout: float = 15.0) -> dict:
    """Helper to send a quick one-shot command to ESPHome Dashboard via WebSocket protocol."""
    reader, writer = await asyncio.open_connection(ESPHOME_HOST, ESPHOME_PORT)
    try:
        req = (
            f"GET /ws HTTP/1.1\r\n"
            f"Host: {ESPHOME_HOST}:{ESPHOME_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(req.encode())
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        def make_frame(msg: str) -> bytes:
            payload = msg.encode('utf-8')
            length = len(payload)
            mask = b"\x12\x34\x56\x78"
            masked_payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
            if length <= 125:
                header = bytes([0x81, 0x80 | length])
            elif length <= 65535:
                header = bytes([0x81, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
            else:
                header = bytes([0x81, 0x80 | 127]) + length.to_bytes(8, 'big')
            return header + mask + masked_payload

        def parse_frames(buf: bytes):
            idx = 0
            frames = []
            while idx < len(buf):
                if idx + 2 > len(buf):
                    break
                b2 = buf[idx + 1]
                length = b2 & 0x7F
                header_len = 2
                if length == 126:
                    if idx + 4 > len(buf):
                        break
                    length = (buf[idx + 2] << 8) | buf[idx + 3]
                    header_len = 4
                elif length == 127:
                    if idx + 10 > len(buf):
                        break
                    header_len = 10
                    length = int.from_bytes(buf[idx + 2 : idx + 10], "big")
                if idx + header_len + length > len(buf):
                    break
                payload_data = buf[idx + header_len : idx + header_len + length]
                frames.append(payload_data.decode("utf-8", errors="ignore"))
                idx += header_len + length
            return frames, buf[idx:]

        # Read server handshake hello
        buf = await reader.read(4096)
        
        msg_id = "1"
        cmd_payload = {"command": command, "message_id": msg_id}
        if args:
            cmd_payload["args"] = args

        writer.write(make_frame(json.dumps(cmd_payload)))
        await writer.drain()

        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            chunk = await asyncio.wait_for(reader.read(16384), timeout=timeout)
            if not chunk:
                break
            buf += chunk
            frames, buf = parse_frames(buf)
            for f in frames:
                try:
                    data = json.loads(f)
                    if data.get("message_id") == msg_id or command in data.get("event", ""):
                        return data
                except json.JSONDecodeError:
                    continue
        return {"error": "Timeout waiting for response"}
    finally:
        writer.close()
        await writer.wait_closed()

async def _stream_ws_process(command: str, args: dict, timeout: float = 300.0) -> str:
    """Silently run an ESPHome build/install job via firmware/follow_job and return once finished."""
    reader, writer = await asyncio.open_connection(ESPHOME_HOST, ESPHOME_PORT)
    start_time = time.time()
    log_lines = []
    
    try:
        req = (
            f"GET /ws HTTP/1.1\r\n"
            f"Host: {ESPHOME_HOST}:{ESPHOME_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(req.encode())
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        def make_frame(msg: str) -> bytes:
            payload = msg.encode('utf-8')
            length = len(payload)
            mask = b"\x12\x34\x56\x78"
            masked_payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
            if length <= 125:
                header = bytes([0x81, 0x80 | length])
            elif length <= 65535:
                header = bytes([0x81, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
            else:
                header = bytes([0x81, 0x80 | 127]) + length.to_bytes(8, 'big')
            return header + mask + masked_payload

        def parse_frames(buf: bytes):
            idx = 0
            frames = []
            while idx < len(buf):
                if idx + 2 > len(buf):
                    break
                b2 = buf[idx + 1]
                length = b2 & 0x7F
                header_len = 2
                if length == 126:
                    if idx + 4 > len(buf):
                        break
                    length = (buf[idx + 2] << 8) | buf[idx + 3]
                    header_len = 4
                elif length == 127:
                    if idx + 10 > len(buf):
                        break
                    header_len = 10
                    length = int.from_bytes(buf[idx + 2 : idx + 10], "big")
                if idx + header_len + length > len(buf):
                    break
                payload_data = buf[idx + header_len : idx + header_len + length]
                frames.append(payload_data.decode("utf-8", errors="ignore"))
                idx += header_len + length
            return frames, buf[idx:]

        # Handshake hello
        buf = await reader.read(4096)

        # 1. Start job (firmware/compile or firmware/install)
        cmd_payload = {"command": command, "message_id": "1", "args": args}
        writer.write(make_frame(json.dumps(cmd_payload)))
        await writer.drain()

        job_id = None
        while (time.time() - start_time) < 15.0:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not chunk:
                break
            buf += chunk
            frames, buf = parse_frames(buf)
            for f in frames:
                try:
                    data = json.loads(f)
                    if data.get("message_id") == "1":
                        res = data.get("result")
                        if isinstance(res, dict) and "job_id" in res:
                            job_id = res["job_id"]
                            break
                except json.JSONDecodeError:
                    continue
            if job_id:
                break

        if not job_id:
            return f"Failed to start ESPHome job for {args.get('configuration')} (No job_id returned)."

        # 2. Follow job logs silently until completion
        cmd_follow = {"command": "firmware/follow_job", "message_id": "2", "args": {"job_id": job_id}}
        writer.write(make_frame(json.dumps(cmd_follow)))
        await writer.drain()

        while (time.time() - start_time) < timeout:
            try:
                chunk = await asyncio.wait_for(reader.read(16384), timeout=10.0)
            except asyncio.TimeoutError:
                continue

            if not chunk:
                break
            buf += chunk
            frames, buf = parse_frames(buf)
            for f in frames:
                try:
                    data = json.loads(f)
                    if data.get("event") == "output" and "data" in data:
                        line = str(data["data"]).strip()
                        if line:
                            log_lines.append(line)

                    # Check for exit event
                    if data.get("event") == "exit":
                        code = data.get("code", 0)
                        elapsed = round(time.time() - start_time, 1)
                        if code == 0:
                            return f"Successfully compiled and flashed {args.get('configuration')} OTA over Wi-Fi! (Took {elapsed}s)"
                        else:
                            return f"Firmware build failed for {args.get('configuration')} (Exit Code {code}).\nError:\n" + "\n".join(log_lines[-10:])

                except json.JSONDecodeError:
                    continue

        elapsed = round(time.time() - start_time, 1)
        return f"Timeout after {elapsed}s waiting for {args.get('configuration')} to finish flashing."

    finally:
        writer.close()
        await writer.wait_closed()

@mcp.tool()
async def esphome_list_devices() -> str:
    """List all ESPHome devices registered in the ESPHome Dashboard, including IP address, status, board, and config YAML filename."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{ESPHOME_HOST}:{ESPHOME_PORT}/devices")
        if resp.status_code == 200:
            devices = resp.json()
            return json.dumps(devices, indent=2)
        return f"Error listing devices: HTTP {resp.status_code}"

@mcp.tool()
async def esphome_get_config(configuration: str) -> str:
    """Retrieve the full YAML configuration for an ESPHome device by file name (e.g. 'esp32-shelf.yaml')."""
    res = await _send_ws_command("devices/get_config", {"configuration": configuration})
    if "result" in res:
        return res["result"]
    return json.dumps(res, indent=2)

@mcp.tool()
async def esphome_update_config(configuration: str, content: str) -> str:
    """Save updated YAML configuration content to an ESPHome device file (e.g. 'esp32-shelf.yaml')."""
    res = await _send_ws_command("devices/update_config", {"configuration": configuration, "content": content})
    if res.get("result") is True or res.get("success") is True or res.get("message_id") == "1":
        return f"Successfully updated configuration for {configuration}"
    return json.dumps(res, indent=2)

@mcp.tool()
async def esphome_validate(configuration: str) -> str:
    """Validate an ESPHome device YAML configuration for syntax and component errors before compilation."""
    res = await _stream_ws_process("firmware/compile", {"configuration": configuration}, timeout=120.0)
    return res

@mcp.tool()
async def esphome_compile(configuration: str) -> str:
    """Trigger C++ compilation for an ESPHome device configuration and wait silently until the build finishes."""
    res = await _stream_ws_process("firmware/compile", {"configuration": configuration}, timeout=180.0)
    return res

@mcp.tool()
async def esphome_flash_ota(configuration: str) -> str:
    """Trigger an Over-The-Air (OTA) firmware build & flash to an ESPHome device and wait silently until complete."""
    res = await _stream_ws_process("firmware/install", {"configuration": configuration, "port": "OTA"}, timeout=300.0)
    return res

if __name__ == "__main__":
    mcp.run()
