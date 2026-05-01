"""
Experimental: Test calling Pencil MCP Server from Python.

This verifies that TAI's backend can programmatically call Pencil's design tools
(batch_design, export_nodes, get_guidelines, etc.) without Claude Code.

Usage:
    # First start the MCP server:
    /Users/yyk956614/.cursor/extensions/highagency.pencildev-0.6.36-universal/out/mcp-server-darwin-arm64 \
        -app cursor -http -http-port 9100

    # Then run this script:
    python experiments/test_pencil_mcp.py
"""

import json
import requests
import sys


MCP_URL = "http://localhost:9100/mcp"


class MCPClient:
    """Simple MCP Streamable HTTP client."""

    def __init__(self, url: str):
        self.url = url
        self.session_id = None
        self._req_id = 0

    def request(self, method: str, params: dict = None) -> dict:
        self._req_id += 1
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        payload = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params:
            payload["params"] = params

        resp = requests.post(self.url, json=payload, headers=headers)

        # Capture session ID from response header
        new_sid = resp.headers.get("Mcp-Session-Id")
        if new_sid:
            self.session_id = new_sid

        print(f"  [{resp.status_code}] {method}" + (f" (session: {self.session_id[:12]}...)" if self.session_id else ""))

        if resp.status_code != 200:
            print(f"  Error: {resp.text[:200]}")
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            result = None
            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "result" in data:
                        result = data["result"]
                    elif "error" in data:
                        print(f"  MCP Error: {data['error']}")
                        return None
            return result
        else:
            data = resp.json()
            if "result" in data:
                return data["result"]
            elif "error" in data:
                print(f"  MCP Error: {data['error']}")
                return None
            return data


def main():
    print("=" * 60)
    print("  Pencil MCP Server — Python Integration Test")
    print("=" * 60)

    client = MCPClient(MCP_URL)

    # Step 1: Initialize session
    print("\n[1] Initializing MCP session...")
    init_result = client.request("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "tai-backend", "version": "0.1.0"}
    })

    if init_result is None:
        print("Failed to initialize. Is the MCP server running?")
        print("Start it with:")
        print("  /path/to/mcp-server-darwin-arm64 -app cursor -http -http-port 9100")
        sys.exit(1)

    print(f"  Server: {json.dumps(init_result.get('serverInfo', {}))}")
    print(f"  Session ID: {client.session_id}")

    # Send initialized notification
    client.request("notifications/initialized")

    # Step 2: List available tools
    print("\n[2] Listing available tools...")
    tools_result = client.request("tools/list")
    if tools_result and "tools" in tools_result:
        for tool in tools_result["tools"]:
            print(f"  - {tool['name']}")
    else:
        print(f"  Raw: {json.dumps(tools_result)[:300] if tools_result else 'None'}")

    # Step 3: Try get_guidelines
    print("\n[3] Calling get_guidelines(topic='slides')...")
    guidelines = client.request("tools/call", {
        "name": "get_guidelines",
        "arguments": {"topic": "slides"}
    })
    if guidelines:
        content = guidelines.get("content", [])
        if content:
            text = content[0].get("text", "")[:200]
            print(f"  Got {len(text)} chars: {text}...")
        else:
            print(f"  Raw: {json.dumps(guidelines)[:300]}")

    # Step 4: Try batch_design on a new file
    print("\n[4] Calling batch_design to create a slide...")
    design_result = client.request("tools/call", {
        "name": "batch_design",
        "arguments": {
            "filePath": "/tmp/tai_test.pen",
            "operations": 'slide=I(document,{type:"frame",name:"Test Slide",width:1920,height:1080,fill:"#0A0F1C",layout:"vertical",placeholder:true})'
        }
    })
    if design_result:
        content = design_result.get("content", [])
        if content:
            print(f"  Result: {content[0].get('text', '')[:200]}")
        else:
            print(f"  Raw: {json.dumps(design_result)[:300]}")

    # Step 5: Try export_nodes
    print("\n[5] Calling export_nodes to export PNG...")
    export_result = client.request("tools/call", {
        "name": "export_nodes",
        "arguments": {
            "filePath": "/tmp/tai_test.pen",
            "outputDir": "/tmp",
            "nodeIds": ["slide"],  # may need actual node ID from step 4
            "format": "png"
        }
    })
    if export_result:
        content = export_result.get("content", [])
        if content:
            print(f"  Result: {content[0].get('text', '')[:200]}")
        else:
            print(f"  Raw: {json.dumps(export_result)[:300]}")

    print("\n" + "=" * 60)
    print("  Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
