package cn.njupt.showcaseserver;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class PythonAgentClient {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };
    private static final Duration POST_TIMEOUT = Duration.ofSeconds(45);

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public PythonAgentClient(
            ObjectMapper objectMapper,
            @Value("${python.agent.base-url:http://127.0.0.1:8000}") String baseUrl
    ) {
        this.objectMapper = objectMapper;
        this.baseUrl = trimTrailingSlash(baseUrl);
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    public ProxyResult get(String path) {
        HttpRequest request = HttpRequest.newBuilder(resolve(path))
                .timeout(Duration.ofSeconds(5))
                .version(HttpClient.Version.HTTP_1_1)
                .GET()
                .build();
        return send(request);
    }

    public ProxyResult post(String path, Map<String, Object> payload) {
        try {
            String json = objectMapper.writeValueAsString(payload);
            return postRaw(path, json);
        } catch (RuntimeException e) {
            return offline("请求序列化失败: " + e.getMessage());
        }
    }

    public ProxyResult postRaw(String path, String json) {
        String payload = (json == null || json.isBlank()) ? "{}" : json;
        HttpRequest request = HttpRequest.newBuilder(resolve(path))
                .timeout(POST_TIMEOUT)
                .version(HttpClient.Version.HTTP_1_1)
                .header("Content-Type", "application/json; charset=utf-8")
                .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                .build();
        return send(request);
    }

    public ProxyResult delete(String path) {
        HttpRequest request = HttpRequest.newBuilder(resolve(path))
                .timeout(Duration.ofSeconds(5))
                .version(HttpClient.Version.HTTP_1_1)
                .DELETE()
                .build();
        return send(request);
    }

    private ProxyResult send(HttpRequest request) {
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            Map<String, Object> body;
            try {
                body = parseBody(response.body());
            } catch (IOException | RuntimeException e) {
                return badResponse(response.statusCode());
            }
            return new ProxyResult(response.statusCode(), body);
        } catch (HttpTimeoutException e) {
            return timeout();
        } catch (IOException e) {
            return offline("Python 服务未启动");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return offline("请求 Python 服务被中断");
        }
    }

    private Map<String, Object> parseBody(String raw) throws IOException {
        if (raw == null || raw.isBlank()) {
            throw new IOException("empty_response");
        }
        return objectMapper.readValue(raw, MAP_TYPE);
    }

    private ProxyResult offline(String message) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "python_offline");
        body.put("message", message);
        body.put("python_base_url", baseUrl);
        return new ProxyResult(HttpStatus.OK.value(), body);
    }

    private ProxyResult timeout() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "python_timeout");
        body.put("message", "Python 响应超时，可能正在加载或执行本地 LLM");
        body.put("python_base_url", baseUrl);
        return new ProxyResult(HttpStatus.OK.value(), body);
    }

    private ProxyResult badResponse(int pythonStatus) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "python_bad_response");
        body.put("message", "Python 返回内容不是有效 JSON");
        body.put("python_status", pythonStatus);
        body.put("python_base_url", baseUrl);
        return new ProxyResult(HttpStatus.OK.value(), body);
    }

    private URI resolve(String path) {
        return URI.create(baseUrl + path);
    }

    public static String encodePath(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    private String trimTrailingSlash(String value) {
        if (value == null || value.isBlank()) {
            return "http://127.0.0.1:8000";
        }
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return trimmed;
    }

    public record ProxyResult(int statusCode, Map<String, Object> body) {
    }
}
