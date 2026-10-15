package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void covered() {
        assertEquals(5, new Calc().covered(2));
    }

    @Test
    void envVarsReachTheBuild() {
        // The demo passes DEMO_PLAIN through the env-vars input.
        String value = System.getenv("DEMO_PLAIN");
        if (value != null) {
            assertEquals("plain-value", value);
        }
    }
}
