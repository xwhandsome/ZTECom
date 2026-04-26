package cn.njupt.showcaseserver;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/showcase/api")
public class ShowcaseProxyController {

    private final PythonAgentClient pythonAgentClient;

    public ShowcaseProxyController(PythonAgentClient pythonAgentClient) {
        this.pythonAgentClient = pythonAgentClient;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return respond(pythonAgentClient.get("/api/health"));
    }

    @PostMapping("/chat")
    public ResponseEntity<Map<String, Object>> chat(@RequestBody Map<String, Object> body) {
        return respond(pythonAgentClient.post("/api/chat", body));
    }

    @PostMapping("/confirm")
    public ResponseEntity<Map<String, Object>> confirm(@RequestBody Map<String, Object> body) {
        return respond(pythonAgentClient.post("/api/confirm", body));
    }

    @GetMapping("/state/{sessionId}")
    public ResponseEntity<Map<String, Object>> state(@PathVariable String sessionId) {
        String encodedSessionId = PythonAgentClient.encodePath(sessionId);
        return respond(pythonAgentClient.get("/api/state/" + encodedSessionId));
    }

    @PostMapping("/reset")
    public ResponseEntity<Map<String, Object>> reset(@RequestBody Map<String, Object> body) {
        return respond(pythonAgentClient.post("/api/reset", body));
    }

    private ResponseEntity<Map<String, Object>> respond(PythonAgentClient.ProxyResult result) {
        return ResponseEntity.status(result.statusCode()).body(result.body());
    }
}
