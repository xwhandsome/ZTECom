package cn.njupt.showcaseserver;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "python.agent.base-url=http://127.0.0.1:9")
class ShowcaseServerApplicationTests {

    @Test
    void contextLoads() {
    }

}
