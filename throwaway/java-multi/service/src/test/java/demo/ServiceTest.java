package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class ServiceTest {
    @Test
    void covered() {
        assertEquals(5, new Service().covered(2));
    }
}
