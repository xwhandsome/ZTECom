package cn.njupt.showcaseserver;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
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
    public ResponseEntity<Map<String, Object>> chat(HttpServletRequest request) {
        return respond(pythonAgentClient.postRaw("/api/chat", readBody(request)));
    }

    @PostMapping("/confirm")
    public ResponseEntity<Map<String, Object>> confirm(HttpServletRequest request) {
        return respond(pythonAgentClient.postRaw("/api/confirm", readBody(request)));
    }

    @GetMapping("/state/{sessionId}")
    public ResponseEntity<Map<String, Object>> state(@PathVariable String sessionId) {
        String encodedSessionId = PythonAgentClient.encodePath(sessionId);
        return respond(pythonAgentClient.get("/api/state/" + encodedSessionId));
    }

    @PostMapping("/reset")
    public ResponseEntity<Map<String, Object>> reset(HttpServletRequest request) {
        return respond(pythonAgentClient.postRaw("/api/reset", readBody(request)));
    }

    @DeleteMapping("/reminders/{sessionId}/{reminderId}")
    public ResponseEntity<Map<String, Object>> deleteReminder(
            @PathVariable String sessionId,
            @PathVariable String reminderId
    ) {
        String path = "/api/reminders/"
                + PythonAgentClient.encodePath(sessionId)
                + "/"
                + PythonAgentClient.encodePath(reminderId);
        return respond(pythonAgentClient.delete(path));
    }

    @PostMapping("/reminders/{sessionId}/{reminderId}/enabled")
    public ResponseEntity<Map<String, Object>> setReminderEnabled(
            @PathVariable String sessionId,
            @PathVariable String reminderId,
            HttpServletRequest request
    ) {
        String path = "/api/reminders/"
                + PythonAgentClient.encodePath(sessionId)
                + "/"
                + PythonAgentClient.encodePath(reminderId)
                + "/enabled";
        return respond(pythonAgentClient.postRaw(path, readBody(request)));
    }

    @DeleteMapping("/env-rules/{sessionId}/{ruleId}")
    public ResponseEntity<Map<String, Object>> deleteEnvRule(
            @PathVariable String sessionId,
            @PathVariable String ruleId
    ) {
        String path = "/api/env-rules/"
                + PythonAgentClient.encodePath(sessionId)
                + "/"
                + PythonAgentClient.encodePath(ruleId);
        return respond(pythonAgentClient.delete(path));
    }

    @PostMapping("/env-rules/{sessionId}/{ruleId}/enabled")
    public ResponseEntity<Map<String, Object>> setEnvRuleEnabled(
            @PathVariable String sessionId,
            @PathVariable String ruleId,
            HttpServletRequest request
    ) {
        String path = "/api/env-rules/"
                + PythonAgentClient.encodePath(sessionId)
                + "/"
                + PythonAgentClient.encodePath(ruleId)
                + "/enabled";
        return respond(pythonAgentClient.postRaw(path, readBody(request)));
    }

    private ResponseEntity<Map<String, Object>> respond(PythonAgentClient.ProxyResult result) {
        return ResponseEntity.status(result.statusCode()).body(result.body());
    }

    private String readBody(HttpServletRequest request) {
        try {
            return new String(request.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
