package cn.njupt.showcaseserver;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class ShowcaseProxyControllerTests {

    private static HttpServer pythonServer;
    private static final String PYTHON_BASE_URL = startPythonServer();

    @AfterAll
    static void stopPythonServer() {
        if (pythonServer != null) {
            pythonServer.stop(0);
        }
    }

    @Test
    void returnsOfflineStatusWhenPythonIsUnavailable() {
        PythonAgentClient client = new PythonAgentClient(new ObjectMapper(), "http://127.0.0.1:9");

        PythonAgentClient.ProxyResult result = client.get("/api/health");

        assertEquals(200, result.statusCode());
        assertEquals("python_offline", result.body().get("status"));
    }

    @Test
    void returnsBadResponseStatusWhenPythonReturnsNonJson() {
        PythonAgentClient client = new PythonAgentClient(new ObjectMapper(), PYTHON_BASE_URL);

        PythonAgentClient.ProxyResult result = client.get("/api/non-json");

        assertEquals(200, result.statusCode());
        assertEquals("python_bad_response", result.body().get("status"));
        assertEquals(200, result.body().get("python_status"));
    }

    @Test
    void proxiesHealth() {
        ShowcaseProxyController controller = controller();

        ResponseEntity<Map<String, Object>> response = controller.health();

        assertEquals(200, response.getStatusCode().value());
        assertNotNull(response.getBody());
        assertEquals("ok", response.getBody().get("status"));
        assertEquals(6, response.getBody().get("kb_chunks"));
    }

    @Test
    void proxiesChatStateResetAndConfirm() {
        ShowcaseProxyController controller = controller();

        ResponseEntity<Map<String, Object>> chat = controller.chat(Map.of(
                "session_id", "demo",
                "user_text", "明早7点提醒奶奶吃降压药",
                "mode", "tool_short"
        ));
        ResponseEntity<Map<String, Object>> state = controller.state("demo");
        ResponseEntity<Map<String, Object>> reset = controller.reset(Map.of("session_id", "demo"));
        ResponseEntity<Map<String, Object>> confirm = controller.confirm(Map.of(
                "session_id", "demo",
                "action_id", "act-1",
                "approved", true
        ));

        assertNotNull(chat.getBody());
        assertEquals("create_reminder", chat.getBody().get("intent"));
        assertEquals("tool_short", chat.getBody().get("mode"));
        assertNotNull(state.getBody());
        assertEquals("demo", state.getBody().get("session_id"));
        assertNotNull(reset.getBody());
        assertEquals("demo", reset.getBody().get("session_id"));
        assertNotNull(confirm.getBody());
        assertEquals("已模拟通知儿子", confirm.getBody().get("assistant_text"));
    }

    private static void respond(HttpExchange exchange, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private ShowcaseProxyController controller() {
        PythonAgentClient client = new PythonAgentClient(new ObjectMapper(), PYTHON_BASE_URL);
        return new ShowcaseProxyController(client);
    }

    private static String startPythonServer() {
        try {
            pythonServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            pythonServer.createContext("/api/health", exchange -> respond(exchange, """
                    {"status":"ok","kb_chunks":6,"llm":{"message":"disabled; runtime_ok"}}
                    """));
            pythonServer.createContext("/api/chat", exchange -> respond(exchange, """
                    {"assistant_text":"已创建用药提醒","mode":"tool_short","intent":"create_reminder","slots":{"medicine":"降压药"},"plan_steps":[],"tool_events":[],"knowledge_refs":[],"requires_confirmation":false,"pending_action":null,"latency_ms":12,"llm_used":false,"llm_status":{"message":"disabled"}}
                    """));
            pythonServer.createContext("/api/confirm", exchange -> respond(exchange, """
                    {"assistant_text":"已模拟通知儿子","tool_events":[{"tool_name":"notify_family","success":true}],"requires_confirmation":false,"pending_action":null}
                    """));
            pythonServer.createContext("/api/state/demo", exchange -> respond(exchange, """
                    {"session_id":"demo","reminders":[],"device_state":{},"sensors":{},"env_rules":[],"recent_tool_events":[]}
                    """));
            pythonServer.createContext("/api/reset", exchange -> respond(exchange, """
                    {"session_id":"demo","state":{"reminders":[]}}
                    """));
            pythonServer.createContext("/api/non-json", exchange -> respond(exchange, "<html>bad gateway</html>"));
            pythonServer.start();
            return "http://127.0.0.1:" + pythonServer.getAddress().getPort();
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }
}
