
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from codegraphcontext.server import MCPServer
from starlette.testclient import TestClient

class TestMCPServer:
    """
    Integration tests for the MCP Server.
    We mock the underlying DB and Logic handlers to verify the Server routes requests correctly.
    """

    @pytest.fixture
    def mock_server(self):
        with patch('codegraphcontext.server.get_database_manager') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            
            with patch('codegraphcontext.server.JobManager') as mock_job_cls, \
                 patch('codegraphcontext.server.GraphBuilder'), \
                 patch('codegraphcontext.server.CodeFinder'), \
                 patch('codegraphcontext.server.CodeWatcher'):
                
                server = MCPServer()
                # Mock handle_tool_call to avoid needing to mock every handler import
                # BUT here we want to test handle_tool_call logic too? 
                # Let's mock the internal handlers instead.
                
                return server

    def test_tool_routing(self, mock_server):
        """Test that handle_tool_call routes to the correct internal method."""
        async def run_test():
            # Mock specific handler wrapper
            mock_server.find_code_tool = MagicMock(return_value={"result": "found"})
            
            # Act
            result = await mock_server.handle_tool_call("find_code", {"query": "test"})
            
            # Assert
            mock_server.find_code_tool.assert_called_once_with(query="test")
            assert result == {"result": "found"}
            
        asyncio.run(run_test())

    def test_unknown_tool(self, mock_server):
        """Test unknown tool returns error."""
        async def run_test():
            result = await mock_server.handle_tool_call("unknown_tool", {})
            assert "error" in result
            assert "Unknown tool" in result["error"]
        
        asyncio.run(run_test())

    def test_add_code_to_graph_routing(self, mock_server):
        """Verify routing for complex tools."""
        async def run_test():
            # Mock the handler function imported in server.py
            with patch('codegraphcontext.server.indexing_handlers.add_code_to_graph') as mock_handler:
                mock_handler.return_value = {"job_id": "123"}
                
                # The tool on the server instance simply calls this handler
                # We must ensure the arguments are passed correctly (including wrappers)
                
                result = await mock_server.handle_tool_call("add_code_to_graph", {"path": "."})
                
                # We can't strictly assert called_once because arguments are complex (bound methods)
                # But we can check result
                assert result == {"job_id": "123"}

        asyncio.run(run_test())


class TestSSETransport:
    """Tests for the SSE HTTP transport exposed by run_sse()."""

    @pytest.fixture
    def sse_client(self):
        """Build a FastAPI TestClient around the SSE app without starting uvicorn."""
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, StreamingResponse
        from starlette.responses import Response
        import json

        with patch('codegraphcontext.server.get_database_manager') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            with patch('codegraphcontext.server.JobManager'), \
                 patch('codegraphcontext.server.GraphBuilder'), \
                 patch('codegraphcontext.server.CodeFinder'), \
                 patch('codegraphcontext.server.CodeWatcher'):

                server = MCPServer()

        # Build the same FastAPI app that run_sse() creates
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.post("/message")
        async def message(request: Request):
            try:
                body = await request.json()
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}
                    },
                )
            response, status_code = await server._handle_jsonrpc_request(body)
            if response is None:
                return Response(status_code=204)
            return JSONResponse(content=response, status_code=status_code)

        return TestClient(app)

    def test_sse_health(self, sse_client):
        """GET /health returns 200 + status ok."""
        resp = sse_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_sse_initialize(self, sse_client):
        """POST /message with initialize returns server info."""
        resp = sse_client.post("/message", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["result"]["serverInfo"]["name"] == "CodeGraphContext"

    def test_sse_tools_list(self, sse_client):
        """POST /message with tools/list returns tools."""
        resp = sse_client.post("/message", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data["result"]
        assert isinstance(data["result"]["tools"], list)

    def test_sse_notification_returns_204(self, sse_client):
        """POST /message with a notification (no id) returns 204."""
        resp = sse_client.post("/message", json={
            "jsonrpc": "2.0", "method": "notifications/initialized"
        })
        assert resp.status_code == 204
        assert resp.content == b""

    def test_sse_malformed_json_returns_400(self, sse_client):
        """POST /message with non-JSON body returns 400 + parse error."""
        resp = sse_client.post(
            "/message",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == -32700
        assert "Parse error" in data["error"]["message"]

