"""
Experiment: Feed TAI's saved prompt directly to Pencil MCP to design a slide,
then use Pencil's code generation guidelines to convert to HTML.

This tests the full pipeline:
  TAI prompt (with references) → Pencil MCP batch_design → .pen slide → export PNG

Usage:
    # Make sure MCP server is running:
    # /path/to/mcp-server-darwin-arm64 -app cursor -http -http-port 9100

    python experiments/pencil_design_from_prompt.py
"""

import json
import requests
import sys


MCP_URL = "http://localhost:9100/mcp"


class MCPClient:
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
        new_sid = resp.headers.get("Mcp-Session-Id")
        if new_sid:
            self.session_id = new_sid

        if resp.status_code != 200:
            print(f"  [{resp.status_code}] {method}: {resp.text[:200]}")
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
            return data.get("result") or data

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool and return the text content."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result and "content" in result:
            texts = [c["text"] for c in result["content"] if c.get("type") == "text"]
            return "\n".join(texts)
        return str(result)


def main():
    # Load saved prompt
    prompt_path = "/tmp/tai_prompts/page_1_interactive.json"
    try:
        with open(prompt_path) as f:
            messages = json.load(f)
    except FileNotFoundError:
        print(f"Prompt file not found: {prompt_path}")
        print("Run the demo first with TAI_DUMP_PROMPTS=/tmp/tai_prompts")
        sys.exit(1)

    user_content = messages[1]["content"]

    print("=" * 60)
    print("  Pencil Design from TAI Prompt")
    print("=" * 60)

    client = MCPClient(MCP_URL)

    # Initialize
    print("\n[1] Connecting to Pencil MCP...")
    client.request("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "tai-experiment", "version": "0.1.0"}
    })
    print(f"  Session: {client.session_id}")

    # Get slide guidelines
    print("\n[2] Getting slide design guidelines...")
    guidelines = client.call_tool("get_guidelines", {"topic": "slides"})
    print(f"  Got {len(guidelines)} chars of guidelines")

    # Get style guide
    print("\n[3] Getting style guide...")
    style = client.call_tool("get_style_guide", {
        "tags": ["dark-mode", "tech", "modern", "gradient", "clean", "bold-typography", "colorful"]
    })
    print(f"  Got {len(style)} chars of style guide")

    # Now design the slide using batch_design
    # We'll create the design based on the prompt content
    print("\n[4] Creating slide design with batch_design...")

    # First create the pen file with open_document
    open_result = client.call_tool("open_document", {"filePathOrTemplate": "new"})
    print(f"  {open_result[:100]}")

    # Get editor state to find the document
    state = client.call_tool("get_editor_state", {"include_schema": False})
    print(f"  Editor state: {state[:200]}")

    # Now create a slide frame based on the prompt
    # The prompt is about "What a higher-order function is and why CS 61A cares"
    print("\n[5] Designing slide: 'What is a Higher-Order Function'...")

    # Phase 1: Create the slide container
    result = client.call_tool("batch_design", {
        "operations": """slide=I(document,{type:"frame",name:"HOF Definition",clip:true,width:1920,height:1080,fill:{type:"gradient",gradientType:"linear",rotation:170,colors:[{color:"#0A0F1C",position:0},{color:"#111827",position:0.6},{color:"#1E293B",position:1}]},layout:"horizontal",padding:[72,88],gap:64,alignItems:"center",placeholder:true})"""
    })
    print(f"  Container: {result[:150]}")

    # Extract the slide node ID from the result
    import re
    node_match = re.search(r'Inserted node `([^`]+)`', result)
    slide_id = node_match.group(1) if node_match else None
    print(f"  Slide ID: {slide_id}")

    if not slide_id:
        print("Failed to get slide ID")
        sys.exit(1)

    # Phase 2: Left column — title + definition
    print("\n  Adding left column...")
    result = client.call_tool("batch_design", {
        "operations": f"""left=I("{slide_id}",{{type:"frame",name:"Left",layout:"vertical",width:720,gap:28}})
label=I(left,{{type:"text",content:"FIRST-CLASS FUNCTIONS",fontFamily:"JetBrains Mono",fontSize:12,fontWeight:"600",fill:"#22D3EE",letterSpacing:2.5}})
title=I(left,{{type:"text",content:"Functions are values.\\nThat changes everything.",fontFamily:"Inter",fontSize:56,fontWeight:"800",fill:"#FFFFFF",lineHeight:1.08,textGrowth:"fixed-width",width:700}})
lead=I(left,{{type:"text",content:"In Python, a function can be stored in a variable, passed as an argument, or returned as a result — just like a number.",fontFamily:"Inter",fontSize:20,fontWeight:"400",fill:"#94A3B8",lineHeight:1.55,textGrowth:"fixed-width",width:620}})
defcard=I(left,{{type:"frame",name:"Definition Card",layout:"vertical",width:"fill_container",fill:"#1E293B",cornerRadius:16,padding:28,gap:20,stroke:{{align:"inside",thickness:1,fill:"#ffffff14"}},effect:{{type:"shadow",shadowType:"outer",color:"#00000030",offset:{{x:0,y:8}},blur:32}}}})
defTitle=I(defcard,{{type:"text",content:"A higher-order function...",fontFamily:"Inter",fontSize:18,fontWeight:"700",fill:"#F1F5F9"}})
items=I(defcard,{{type:"frame",name:"Items",layout:"vertical",width:"fill_container",gap:14}})
row1=I(items,{{type:"frame",layout:"horizontal",width:"fill_container",gap:14,alignItems:"center"}})
icon1=I(row1,{{type:"frame",width:32,height:32,cornerRadius:16,fill:{{type:"gradient",gradientType:"linear",rotation:135,colors:[{{color:"#22D3EE",position:0}},{{color:"#0891B2",position:1}}]}},justifyContent:"center",alignItems:"center"}})
i1=I(icon1,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"arrow-right",width:16,height:16,fill:"#0A0F1C"}})
t1=I(row1,{{type:"text",content:"Takes a function as an argument",fontFamily:"Inter",fontSize:16,fontWeight:"500",fill:"#94A3B8"}})
row2=I(items,{{type:"frame",layout:"horizontal",width:"fill_container",gap:14,alignItems:"center"}})
icon2=I(row2,{{type:"frame",width:32,height:32,cornerRadius:16,fill:{{type:"gradient",gradientType:"linear",rotation:135,colors:[{{color:"#A78BFA",position:0}},{{color:"#7C3AED",position:1}}]}},justifyContent:"center",alignItems:"center"}})
i2=I(icon2,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"arrow-left",width:16,height:16,fill:"#0A0F1C"}})
t2=I(row2,{{type:"text",content:"Returns a function as a result",fontFamily:"Inter",fontSize:16,fontWeight:"500",fill:"#94A3B8"}})
row3=I(items,{{type:"frame",layout:"horizontal",width:"fill_container",gap:14,alignItems:"center"}})
icon3=I(row3,{{type:"frame",width:32,height:32,cornerRadius:16,fill:{{type:"gradient",gradientType:"linear",rotation:135,colors:[{{color:"#34D399",position:0}},{{color:"#059669",position:1}}]}},justifyContent:"center",alignItems:"center"}})
i3=I(icon3,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"repeat",width:16,height:16,fill:"#0A0F1C"}})
t3=I(row3,{{type:"text",content:"Or both",fontFamily:"Inter",fontSize:16,fontWeight:"500",fill:"#94A3B8"}})"""
    })
    print(f"  Left column: {result[:150]}")

    # Phase 3: Right column — code card + why card
    print("\n  Adding right column...")
    result = client.call_tool("batch_design", {
        "operations": f"""right=I("{slide_id}",{{type:"frame",name:"Right",layout:"vertical",width:"fill_container",gap:20}})
codeCard=I(right,{{type:"frame",name:"Code Card",layout:"vertical",width:"fill_container",fill:"#1E293B",cornerRadius:16,stroke:{{align:"inside",thickness:1,fill:"#ffffff14"}},effect:{{type:"shadow",shadowType:"outer",color:"#00000030",offset:{{x:0,y:8}},blur:32}},clip:true}})
cHead=I(codeCard,{{type:"frame",layout:"horizontal",width:"fill_container",padding:[16,24],gap:12,alignItems:"center"}})
badge=I(cHead,{{type:"frame",padding:[5,12],cornerRadius:100,fill:{{type:"gradient",gradientType:"linear",rotation:135,colors:[{{color:"#22D3EE",position:0}},{{color:"#0891B2",position:1}}]}}}})
badgeTxt=I(badge,{{type:"text",content:"PATTERN 1",fontFamily:"JetBrains Mono",fontSize:10,fontWeight:"700",fill:"#0A0F1C",letterSpacing:1.5}})
cLabel=I(cHead,{{type:"text",content:"Function as argument",fontFamily:"Inter",fontSize:15,fontWeight:"600",fill:"#F1F5F9"}})
cBody=I(codeCard,{{type:"frame",layout:"vertical",width:"fill_container",padding:[4,24,24,24]}})
c1=I(cBody,{{type:"text",content:"def apply_twice(f, x):",fontFamily:"JetBrains Mono",fontSize:15,fill:"#A78BFA",lineHeight:1.7}})
c2=I(cBody,{{type:"text",content:"    return f(f(x))",fontFamily:"JetBrains Mono",fontSize:15,fill:"#E2E8F0",lineHeight:1.7}})
c3=I(cBody,{{type:"text",content:" ",fontFamily:"JetBrains Mono",fontSize:15,fill:"#E2E8F0",lineHeight:1.7}})
c4=I(cBody,{{type:"text",content:"apply_twice(square, 3)  # → 81",fontFamily:"JetBrains Mono",fontSize:15,fill:"#64748B",lineHeight:1.7}})
cFoot=I(codeCard,{{type:"frame",layout:"horizontal",width:"fill_container",padding:[12,24,20,24],gap:8,alignItems:"center",fill:"#0F172A"}})
pill=I(cFoot,{{type:"frame",padding:[3,10],cornerRadius:100,fill:"#22D3EE18",stroke:{{align:"inside",thickness:1,fill:"#22D3EE40"}}}})
pillTxt=I(pill,{{type:"text",content:"f",fontFamily:"JetBrains Mono",fontSize:13,fontWeight:"600",fill:"#22D3EE"}})
footTxt=I(cFoot,{{type:"text",content:"is a function passed in — that makes it higher-order.",fontFamily:"Inter",fontSize:14,fill:"#94A3B8"}})
whyCard=I(right,{{type:"frame",name:"Why Card",layout:"vertical",width:"fill_container",fill:"#1E293B",cornerRadius:16,padding:24,gap:16,stroke:{{align:"inside",thickness:1,fill:"#ffffff14"}},effect:{{type:"shadow",shadowType:"outer",color:"#00000030",offset:{{x:0,y:8}},blur:32}}}})
whyH=I(whyCard,{{type:"frame",layout:"horizontal",gap:10,alignItems:"center"}})
whyI=I(whyH,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"lightbulb",width:20,height:20,fill:"#34D399"}})
whyT=I(whyH,{{type:"text",content:"Why CS 61A cares",fontFamily:"Inter",fontSize:16,fontWeight:"700",fill:"#34D399"}})
whyItems=I(whyCard,{{type:"frame",layout:"vertical",width:"fill_container",gap:12}})
w1=I(whyItems,{{type:"frame",layout:"horizontal",gap:12,alignItems:"center"}})
w1i=I(w1,{{type:"frame",width:28,height:28,cornerRadius:6,fill:"#22D3EE18",justifyContent:"center",alignItems:"center"}})
w1ic=I(w1i,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"layers",width:14,height:14,fill:"#22D3EE"}})
w1t=I(w1,{{type:"text",content:"Abstraction — express general computation methods",fontFamily:"Inter",fontSize:14,fill:"#94A3B8"}})
w2=I(whyItems,{{type:"frame",layout:"horizontal",gap:12,alignItems:"center"}})
w2i=I(w2,{{type:"frame",width:28,height:28,cornerRadius:6,fill:"#A78BFA18",justifyContent:"center",alignItems:"center"}})
w2ic=I(w2i,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"grid-2x2",width:14,height:14,fill:"#A78BFA"}})
w2t=I(w2,{{type:"text",content:"Modularity — one function, one job",fontFamily:"Inter",fontSize:14,fill:"#94A3B8"}})
w3=I(whyItems,{{type:"frame",layout:"horizontal",gap:12,alignItems:"center"}})
w3i=I(w3,{{type:"frame",width:28,height:28,cornerRadius:6,fill:"#FBBF2418",justifyContent:"center",alignItems:"center"}})
w3ic=I(w3i,{{type:"icon_font",iconFontFamily:"lucide",iconFontName:"copy",width:14,height:14,fill:"#FBBF24"}})
w3t=I(w3,{{type:"text",content:"No repetition — write the pattern once",fontFamily:"Inter",fontSize:14,fill:"#94A3B8"}})"""
    })
    print(f"  Right column: {result[:150]}")

    # Remove placeholder
    print("\n[6] Finalizing slide...")
    client.call_tool("batch_design", {
        "operations": f'U("{slide_id}",{{placeholder:false}})'
    })

    # Export to PNG
    print("\n[7] Exporting to PNG...")
    export = client.call_tool("export_nodes", {
        "outputDir": "/tmp/pencil_experiment",
        "nodeIds": [slide_id],
        "format": "png",
        "scale": 2
    })
    print(f"  Export: {export}")

    # Take screenshot
    print("\n[8] Taking screenshot...")
    screenshot = client.call_tool("get_screenshot", {"nodeId": slide_id})
    print(f"  Screenshot: {screenshot[:100] if screenshot else 'None'}")

    print("\n" + "=" * 60)
    print(f"  Done! Check /tmp/pencil_experiment/{slide_id}.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
