"""Reference MCP server (official SDK 1.x) used to test the script's MCP clients. Usage: mock_mcp_server.py <transport> <port> <toolset>"""
import sys
from mcp.server.fastmcp import FastMCP

transport, port, toolset = sys.argv[1], int(sys.argv[2]), sys.argv[3]
srv = FastMCP("mock", host="127.0.0.1", port=port)

if toolset == "paypal":
    @srv.tool()
    def get_order(payment_id: str) -> str:
        """Get an order"""
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:9400/v2/checkout/orders/{payment_id}", headers={"Authorization": "Bearer x"})
        return urllib.request.urlopen(req, timeout=10).read().decode()

    @srv.tool()
    def create_order(items: str) -> str:
        """write tool"""
        return "x"

    @srv.tool()
    def list_transaction(start_date: str = "", end_date: str = "") -> str:
        """list"""
        return "[]"
elif toolset == "zapier4":
    for n in ("list_pools", "join_pool", "list_entries", "withdraw_entry"):
        exec(f"@srv.tool(name='{n}')\ndef _t_{n}(body: str = '', query: str = '') -> str:\n    '''{n}'''\n    return 'ok'")
elif toolset == "zapier_agentic":
    for n in ("discover_zapier_actions", "enable_zapier_action", "list_pools"):
        exec(f"@srv.tool(name='{n}')\ndef _t_{n}(q: str = '') -> str:\n    '''{n}'''\n    return 'ok'")
srv.run(transport=transport)
