package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class CoreTest {
    @Test
    void twice() {
        assertEquals(4, new Core().twice(2));
    }
}
