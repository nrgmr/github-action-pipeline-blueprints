package demo;

/** Throwaway class for the coverage gate demo. Half of it is tested on purpose. */
public class Calc {
    public int covered(int value) {
        int doubled = value * 2;
        return doubled + 1;
    }

    public int uncovered(int value) {
        int tripled = value * 3;
        return tripled + 1;
    }
}
